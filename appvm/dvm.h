#define DBDIR "/home/user/.dvm"
struct dvm_header {
unsigned long long file_size;
char name[1024-sizeof(unsigned long long)];
};

