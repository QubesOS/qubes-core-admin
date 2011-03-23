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

char * copy_file(int outfd, int infd, long long size);
