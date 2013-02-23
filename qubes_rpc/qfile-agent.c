#define _GNU_SOURCE
#include <dirent.h>
#include <stdio.h>
#include <string.h>
#include <sys/stat.h>
#include <signal.h>
#include <fcntl.h>
#include <malloc.h>
#include <stdlib.h>
#include <ioall.h>
#include <unistd.h>
#include <errno.h>
#include <gui-fatal.h>
#include "filecopy.h"
#include "crc32.h"

enum {
	PROGRESS_FLAG_NORMAL,
	PROGRESS_FLAG_INIT,
	PROGRESS_FLAG_DONE
};

unsigned long crc32_sum;
int write_all_with_crc(int fd, void *buf, int size)
{
	crc32_sum = Crc32_ComputeBuf(crc32_sum, buf, size);
	return write_all(fd, buf, size);
}

void do_notify_progress(long long total, int flag)
{
	char *du_size_env = getenv("FILECOPY_TOTAL_SIZE");
	char *progress_type_env = getenv("PROGRESS_TYPE");
	char *saved_stdout_env = getenv("SAVED_FD_1");
	if (!progress_type_env)
		return;
	if (!strcmp(progress_type_env, "console") && du_size_env) {
		char msg[256];
		snprintf(msg, sizeof(msg), "sent %lld/%lld KB\r",
			 total / 1024, strtoull(du_size_env, NULL, 0));
		write(2, msg, strlen(msg));
		if (flag == PROGRESS_FLAG_DONE)
			write(2, "\n", 1);
	}
	if (!strcmp(progress_type_env, "gui") && saved_stdout_env) {
		char msg[256];
		snprintf(msg, sizeof(msg), "%lld\n", total);
		write(strtoul(saved_stdout_env, NULL, 0), msg,
		      strlen(msg));
	}
}

void wait_for_result()
{
	struct result_header hdr;

	if (!read_all(0, &hdr, sizeof(hdr))) {
		if (errno == EAGAIN) {
			// no result sent and stdin still open
			return;
		} else {
			// other read error or EOF
			exit(1);	// hopefully remote has produced error message
		}
	}
	if (hdr.error_code != 0) {
		switch (hdr.error_code) {
			case EEXIST:
				gui_fatal("File copy: not overwriting existing file. Clean QubesIncoming dir, and retry copy");
				break;
			case EINVAL:
				gui_fatal("File copy: Corrupted data from packer");
				break;
			default:
				gui_fatal("File copy: %s",
						strerror(hdr.error_code));
		}
	}
	if (hdr.crc32 != crc32_sum) {
		gui_fatal("File transfer failed: checksum mismatch");
	}
}

void notify_progress(int size, int flag)
{
	static long long total = 0;
	static long long prev_total = 0;
	total += size;
	if (total > prev_total + PROGRESS_NOTIFY_DELTA
	    || (flag != PROGRESS_FLAG_NORMAL)) {
		// check for possible error from qfile-unpacker; if error occured,
		// exit() will be called, so don't bother with current state
		// (notify_progress can be called as callback from copy_file())
		if (flag == PROGRESS_FLAG_NORMAL)
			wait_for_result();
		do_notify_progress(total, flag);
		prev_total = total;
	}
}

void write_headers(struct file_header *hdr, char *filename)
{
	if (!write_all_with_crc(1, hdr, sizeof(*hdr))
	    || !write_all_with_crc(1, filename, hdr->namelen)) {
		set_block(0);
		wait_for_result();
		exit(1);
	}
}

int single_file_processor(char *filename, struct stat *st)
{
	struct file_header hdr;
	int fd;
	mode_t mode = st->st_mode;

	hdr.namelen = strlen(filename) + 1;
	hdr.mode = mode;
	hdr.atime = st->st_atim.tv_sec;
	hdr.atime_nsec = st->st_atim.tv_nsec;
	hdr.mtime = st->st_mtim.tv_sec;
	hdr.mtime_nsec = st->st_mtim.tv_nsec;

	if (S_ISREG(mode)) {
		int ret;
		fd = open(filename, O_RDONLY);
		if (fd < 0)
			gui_fatal("open %s", filename);
		hdr.filelen = st->st_size;
		write_headers(&hdr, filename);
		ret = copy_file(1, fd, hdr.filelen, &crc32_sum);
		if (ret != COPY_FILE_OK) {
			if (ret != COPY_FILE_WRITE_ERROR)
				gui_fatal("Copying file %s: %s", filename,
					  copy_file_status_to_str(ret));
			else {
				set_block(0);
				wait_for_result();
				exit(1);
			}
		}
		close(fd);
	}
	if (S_ISDIR(mode)) {
		hdr.filelen = 0;
		write_headers(&hdr, filename);
	}
	if (S_ISLNK(mode)) {
		char name[st->st_size + 1];
		if (readlink(filename, name, sizeof(name)) != st->st_size)
			gui_fatal("readlink %s", filename);
		hdr.filelen = st->st_size + 1;
		write_headers(&hdr, filename);
		if (!write_all_with_crc(1, name, st->st_size + 1)) {
			set_block(0);
			wait_for_result();
			exit(1);
		}
	}
	// check for possible error from qfile-unpacker
	wait_for_result();
	return 0;
}

int do_fs_walk(char *file)
{
	char *newfile;
	struct stat st;
	struct dirent *ent;
	DIR *dir;

	if (lstat(file, &st))
		gui_fatal("stat %s", file);
	single_file_processor(file, &st);
	if (!S_ISDIR(st.st_mode))
		return 0;
	dir = opendir(file);
	if (!dir)
		gui_fatal("opendir %s", file);
	while ((ent = readdir(dir))) {
		char *fname = ent->d_name;
		if (!strcmp(fname, ".") || !strcmp(fname, ".."))
			continue;
		asprintf(&newfile, "%s/%s", file, fname);
		do_fs_walk(newfile);
		free(newfile);
	}
	closedir(dir);
	// directory metadata is resent; this makes the code simple,
	// and the atime/mtime is set correctly at the second time
	single_file_processor(file, &st);
	return 0;
}

void notify_end_and_wait_for_result()
{
	struct file_header end_hdr;

	/* nofity end of transfer */
	memset(&end_hdr, 0, sizeof(end_hdr));
	end_hdr.namelen = 0;
	end_hdr.filelen = 0;
	write_all_with_crc(1, &end_hdr, sizeof(end_hdr));

	set_block(0);
	wait_for_result();
}

char *get_abs_path(char *cwd, char *pathname)
{
	char *ret;
	if (pathname[0] == '/')
		return strdup(pathname);
	asprintf(&ret, "%s/%s", cwd, pathname);
	return ret;
}

int main(int argc, char **argv)
{
	int i;
	char *entry;
	char *cwd;
	char *sep;

	signal(SIGPIPE, SIG_IGN);
	// this will allow checking for possible feedback packet in the middle of transfer
	set_nonblock(0);
	notify_progress(0, PROGRESS_FLAG_INIT);
	crc32_sum = 0;
	cwd = getcwd(NULL, 0);
	for (i = 1; i < argc; i++) {
		entry = get_abs_path(cwd, argv[i]);

		do {
			sep = rindex(entry, '/');
			if (!sep)
				gui_fatal
				    ("Internal error: nonabsolute filenames not allowed");
			*sep = 0;
		} while (sep[1] == 0);
		if (entry[0] == 0)
			chdir("/");
		else if (chdir(entry))
			gui_fatal("chdir to %s", entry);
		do_fs_walk(sep + 1);
		free(entry);
	}
	notify_end_and_wait_for_result();
	notify_progress(0, PROGRESS_FLAG_DONE);
	return 0;
}
