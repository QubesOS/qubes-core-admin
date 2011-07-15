#define FILECOPY_SPOOL "/home/user/.filecopyspool"
#define FILECOPY_VMNAME_SIZE 32
#define PROGRESS_NOTIFY_DELTA (15*1000*1000)
#define MAX_PATH_LENGTH 16384

#define LEGAL_EOF 31415926

struct file_header {
	unsigned int namelen;
	unsigned int mode;
	unsigned long long filelen;
	unsigned int atime;
	unsigned int atime_nsec;
	unsigned int mtime;
	unsigned int mtime_nsec;
};

struct result_header {
	unsigned int error_code;
	unsigned long crc32;
};

enum {
	COPY_FILE_OK,
	COPY_FILE_READ_EOF,
	COPY_FILE_READ_ERROR,
	COPY_FILE_WRITE_ERROR
};

int copy_file(int outfd, int infd, long long size, unsigned long *crc32);
char *copy_file_status_to_str(int status);
void set_size_limit(long long new_bytes_limit, long long new_files_limit);
