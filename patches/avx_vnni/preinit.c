/*
 * Minimal freestanding x86-64 baseline PID-1 pre-init wrapper for Googlebook OS.
 *
 * Loads /lib/modules/avx_vnni_emu.ko into the kernel BEFORE /init executes its
 * first instruction, preventing early #UD (SIGILL) kernel panics on CPUs that
 * lack Alder Lake ISA extensions (GFNI / AVX-VNNI / VAES / VPCLMULQDQ / SHA-NI),
 * such as AMD Ryzen Zen 1/2/3 and Intel 6th-10th Gen (Skylake - Comet Lake).
 */

typedef unsigned long u64;
typedef long s64;

static inline s64 sys1(s64 nr, s64 a1) {
    s64 ret;
    __asm__ volatile("syscall" : "=a"(ret) : "a"(nr), "D"(a1) : "rcx", "r11", "memory");
    return ret;
}

static inline s64 sys3(s64 nr, s64 a1, s64 a2, s64 a3) {
    s64 ret;
    __asm__ volatile("syscall" : "=a"(ret) : "a"(nr), "D"(a1), "S"(a2), "d"(a3) : "rcx", "r11", "memory");
    return ret;
}

static inline s64 sys4(s64 nr, s64 a1, s64 a2, s64 a3, s64 a4) {
    s64 ret;
    register s64 r10 __asm__("r10") = a4;
    __asm__ volatile("syscall" : "=a"(ret) : "a"(nr), "D"(a1), "S"(a2), "d"(a3), "r"(r10) : "rcx", "r11", "memory");
    return ret;
}

#define NR_read         0
#define NR_close        3
#define NR_lseek        8
#define NR_execve       59
#define NR_init_module  175
#define NR_openat       257
#define NR_finit_module 313
#define AT_FDCWD        (-100)
#define O_RDONLY        0

static unsigned char ko_buf[65536];

__attribute__((used, noreturn))
void preinit_main(u64 *sp) {
    static const char ko_path[] = "/lib/modules/avx_vnni_emu.ko";
    static const char empty_opts[] = "";
    static const char real_init[] = "/init";

    s64 fd = sys4(NR_openat, AT_FDCWD, (s64)ko_path, O_RDONLY, 0);
    if (fd >= 0) {
        s64 rc = sys3(NR_finit_module, fd, (s64)empty_opts, 0);
        if (rc < 0) {
            sys3(NR_lseek, fd, 0, 0);
            s64 total = 0;
            while (total < (s64)sizeof(ko_buf)) {
                s64 n = sys3(NR_read, fd, (s64)(ko_buf + total), (s64)sizeof(ko_buf) - total);
                if (n <= 0)
                    break;
                total += n;
            }
            if (total > 0)
                sys3(NR_init_module, (s64)ko_buf, total, (s64)empty_opts);
        }
        sys1(NR_close, fd);
    }

    u64 argc = sp[0];
    char **argv = (char **)&sp[1];
    char **envp = &argv[argc + 1];
    argv[0] = (char *)real_init;

    sys3(NR_execve, (s64)real_init, (s64)argv, (s64)envp);

    for (;;)
        __asm__ volatile("ud2");
}

__asm__(
    ".section .text,\"ax\",@progbits\n"
    ".globl _start\n"
    ".type _start, @function\n"
    "_start:\n"
    "    xor %rbp, %rbp\n"
    "    mov %rsp, %rdi\n"
    "    and $-16, %rsp\n"
    "    call preinit_main\n"
);
