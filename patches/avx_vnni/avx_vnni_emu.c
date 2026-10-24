typedef unsigned char u8;
typedef signed char s8;
typedef unsigned short u16;
typedef signed short s16;
typedef unsigned int u32;
typedef signed int s32;
typedef unsigned long long u64;
typedef signed long long s64;

struct pt_regs {
    u64 r15, r14, r13, r12, bp, bx, r11, r10, r9, r8;
    u64 ax, cx, dx, si, di, orig_ax;
    u64 ip, cs, flags, sp, ss;
};

struct notifier_block {
    int (*notifier_call)(struct notifier_block *nb, unsigned long action, void *data);
    struct notifier_block *next;
    int priority;
};

struct die_args {
    struct pt_regs *regs;
    const char *str;
    long err;
    int trapnr;
    int signr;
};

extern int register_die_notifier(struct notifier_block *nb);
extern int unregister_die_notifier(struct notifier_block *nb);
extern long copy_from_user_nofault(void *dst, const void *src, unsigned long size);
extern void switch_fpu_return(void);
extern int _printk(const char *fmt, ...);

#define NOTIFY_DONE 0x0000
#define NOTIFY_STOP 0x8001
#define DIE_TRAP    8
#define X86_TRAP_UD 6

extern int vnni_die_handler(struct notifier_block *nb, unsigned long action, void *data);

/* kCFI + FineIBT trampolines matching Cuttlefish 6.12.74-android16-6 */
__asm__(
    ".section .text,\"ax\",@progbits\n"
    ".p2align 4\n"
    "__cfi_vnni_die_handler:\n"
    "    .byte 0xb8, 0x3b, 0x7a, 0x12, 0xd5\n"
    "    .fill 11, 1, 0x90\n"
    ".globl vnni_die_handler\n"
    ".type vnni_die_handler, @function\n"
    "vnni_die_handler:\n"
    "    endbr64\n"
    "    jmp vnni_die_handler_impl\n"

    ".section .init.text,\"ax\",@progbits\n"
    ".p2align 4\n"
    "__cfi_init_module:\n"
    "    .byte 0xb8, 0x35, 0x30, 0xbb, 0x6f\n"
    "    .fill 11, 1, 0x90\n"
    ".globl init_module\n"
    ".type init_module, @function\n"
    "init_module:\n"
    "    endbr64\n"
    "    jmp init_module_impl\n"

    ".section .exit.text,\"ax\",@progbits\n"
    ".p2align 4\n"
    "__cfi_cleanup_module:\n"
    "    .byte 0xb8, 0x60, 0x7d, 0xc4, 0xe5\n"
    "    .fill 11, 1, 0x90\n"
    ".globl cleanup_module\n"
    ".type cleanup_module, @function\n"
    "cleanup_module:\n"
    "    endbr64\n"
    "    jmp cleanup_module_impl\n"
);

/* Direct-branch VEX vmovdqu helpers (compiled with -fno-jump-tables: zero indirect jumps) */
static __attribute__((noinline)) void get_ymm(int reg, void *buf) {
    switch (reg & 15) {
        case  0: __asm__ volatile(".byte 0xc5,0xfe,0x7f,0x06" :: "S"(buf) : "memory"); break;
        case  1: __asm__ volatile(".byte 0xc5,0xfe,0x7f,0x0e" :: "S"(buf) : "memory"); break;
        case  2: __asm__ volatile(".byte 0xc5,0xfe,0x7f,0x16" :: "S"(buf) : "memory"); break;
        case  3: __asm__ volatile(".byte 0xc5,0xfe,0x7f,0x1e" :: "S"(buf) : "memory"); break;
        case  4: __asm__ volatile(".byte 0xc5,0xfe,0x7f,0x26" :: "S"(buf) : "memory"); break;
        case  5: __asm__ volatile(".byte 0xc5,0xfe,0x7f,0x2e" :: "S"(buf) : "memory"); break;
        case  6: __asm__ volatile(".byte 0xc5,0xfe,0x7f,0x36" :: "S"(buf) : "memory"); break;
        case  7: __asm__ volatile(".byte 0xc5,0xfe,0x7f,0x3e" :: "S"(buf) : "memory"); break;
        case  8: __asm__ volatile(".byte 0xc5,0x7e,0x7f,0x06" :: "S"(buf) : "memory"); break;
        case  9: __asm__ volatile(".byte 0xc5,0x7e,0x7f,0x0e" :: "S"(buf) : "memory"); break;
        case 10: __asm__ volatile(".byte 0xc5,0x7e,0x7f,0x16" :: "S"(buf) : "memory"); break;
        case 11: __asm__ volatile(".byte 0xc5,0x7e,0x7f,0x1e" :: "S"(buf) : "memory"); break;
        case 12: __asm__ volatile(".byte 0xc5,0x7e,0x7f,0x26" :: "S"(buf) : "memory"); break;
        case 13: __asm__ volatile(".byte 0xc5,0x7e,0x7f,0x2e" :: "S"(buf) : "memory"); break;
        case 14: __asm__ volatile(".byte 0xc5,0x7e,0x7f,0x36" :: "S"(buf) : "memory"); break;
        default: __asm__ volatile(".byte 0xc5,0x7e,0x7f,0x3e" :: "S"(buf) : "memory"); break;
    }
}

static __attribute__((noinline)) void set_ymm(int reg, const void *buf) {
    switch (reg & 15) {
        case  0: __asm__ volatile(".byte 0xc5,0xfe,0x6f,0x06" :: "S"(buf) : "memory"); break;
        case  1: __asm__ volatile(".byte 0xc5,0xfe,0x6f,0x0e" :: "S"(buf) : "memory"); break;
        case  2: __asm__ volatile(".byte 0xc5,0xfe,0x6f,0x16" :: "S"(buf) : "memory"); break;
        case  3: __asm__ volatile(".byte 0xc5,0xfe,0x6f,0x1e" :: "S"(buf) : "memory"); break;
        case  4: __asm__ volatile(".byte 0xc5,0xfe,0x6f,0x26" :: "S"(buf) : "memory"); break;
        case  5: __asm__ volatile(".byte 0xc5,0xfe,0x6f,0x2e" :: "S"(buf) : "memory"); break;
        case  6: __asm__ volatile(".byte 0xc5,0xfe,0x6f,0x36" :: "S"(buf) : "memory"); break;
        case  7: __asm__ volatile(".byte 0xc5,0xfe,0x6f,0x3e" :: "S"(buf) : "memory"); break;
        case  8: __asm__ volatile(".byte 0xc5,0x7e,0x6f,0x06" :: "S"(buf) : "memory"); break;
        case  9: __asm__ volatile(".byte 0xc5,0x7e,0x6f,0x0e" :: "S"(buf) : "memory"); break;
        case 10: __asm__ volatile(".byte 0xc5,0x7e,0x6f,0x16" :: "S"(buf) : "memory"); break;
        case 11: __asm__ volatile(".byte 0xc5,0x7e,0x6f,0x1e" :: "S"(buf) : "memory"); break;
        case 12: __asm__ volatile(".byte 0xc5,0x7e,0x6f,0x26" :: "S"(buf) : "memory"); break;
        case 13: __asm__ volatile(".byte 0xc5,0x7e,0x6f,0x2e" :: "S"(buf) : "memory"); break;
        case 14: __asm__ volatile(".byte 0xc5,0x7e,0x6f,0x36" :: "S"(buf) : "memory"); break;
        default: __asm__ volatile(".byte 0xc5,0x7e,0x6f,0x3e" :: "S"(buf) : "memory"); break;
    }
}

static __attribute__((noinline)) void set_xmm(int reg, const void *buf) {
    switch (reg & 15) {
        case  0: __asm__ volatile(".byte 0xc5,0xfa,0x6f,0x06" :: "S"(buf) : "memory"); break;
        case  1: __asm__ volatile(".byte 0xc5,0xfa,0x6f,0x0e" :: "S"(buf) : "memory"); break;
        case  2: __asm__ volatile(".byte 0xc5,0xfa,0x6f,0x16" :: "S"(buf) : "memory"); break;
        case  3: __asm__ volatile(".byte 0xc5,0xfa,0x6f,0x1e" :: "S"(buf) : "memory"); break;
        case  4: __asm__ volatile(".byte 0xc5,0xfa,0x6f,0x26" :: "S"(buf) : "memory"); break;
        case  5: __asm__ volatile(".byte 0xc5,0xfa,0x6f,0x2e" :: "S"(buf) : "memory"); break;
        case  6: __asm__ volatile(".byte 0xc5,0xfa,0x6f,0x36" :: "S"(buf) : "memory"); break;
        case  7: __asm__ volatile(".byte 0xc5,0xfa,0x6f,0x3e" :: "S"(buf) : "memory"); break;
        case  8: __asm__ volatile(".byte 0xc5,0x7a,0x6f,0x06" :: "S"(buf) : "memory"); break;
        case  9: __asm__ volatile(".byte 0xc5,0x7a,0x6f,0x0e" :: "S"(buf) : "memory"); break;
        case 10: __asm__ volatile(".byte 0xc5,0x7a,0x6f,0x16" :: "S"(buf) : "memory"); break;
        case 11: __asm__ volatile(".byte 0xc5,0x7a,0x6f,0x1e" :: "S"(buf) : "memory"); break;
        case 12: __asm__ volatile(".byte 0xc5,0x7a,0x6f,0x26" :: "S"(buf) : "memory"); break;
        case 13: __asm__ volatile(".byte 0xc5,0x7a,0x6f,0x2e" :: "S"(buf) : "memory"); break;
        case 14: __asm__ volatile(".byte 0xc5,0x7a,0x6f,0x36" :: "S"(buf) : "memory"); break;
        default: __asm__ volatile(".byte 0xc5,0x7a,0x6f,0x3e" :: "S"(buf) : "memory"); break;
    }
}

static inline int avx_state_usable(void) {
    u64 cr0;
    u32 xcr0_lo, xcr0_hi;
    __asm__ volatile("movq %%cr0, %0" : "=r"(cr0));
    if (cr0 & 8ULL) /* CR0.TS */
        return 0;
    __asm__ volatile(".byte 0x0f, 0x01, 0xd0" : "=a"(xcr0_lo), "=d"(xcr0_hi) : "c"(0));
    return (xcr0_lo & 6U) == 6U;
}

static u64 get_gpr(const struct pt_regs *r, int idx) {
    switch (idx & 15) {
        case  0: return r->ax;
        case  1: return r->cx;
        case  2: return r->dx;
        case  3: return r->bx;
        case  4: return r->sp;
        case  5: return r->bp;
        case  6: return r->si;
        case  7: return r->di;
        case  8: return r->r8;
        case  9: return r->r9;
        case 10: return r->r10;
        case 11: return r->r11;
        case 12: return r->r12;
        case 13: return r->r13;
        case 14: return r->r14;
        default: return r->r15;
    }
}

static inline s32 sat_s32(s64 v) {
    if (v > 2147483647LL) return 2147483647;
    if (v < -2147483648LL) return (s32)(-2147483647 - 1);
    return (s32)v;
}

union vec256 {
    u8  u8v[32];
    s8  s8v[32];
    s16 s16v[16];
    s32 s32v[8];
    u32 u32v[8];
    u64 u64v[4];
};

__attribute__((used))
int vnni_die_handler_impl(struct notifier_block *nb, unsigned long action, void *data) {
    struct die_args *args = (struct die_args *)data;
    struct pt_regs *regs;
    u8 insn[15];
    int avail = 15;

    (void)nb;
    if (action != DIE_TRAP || !args)
        return NOTIFY_DONE;
    regs = args->regs;
    if (!regs || args->trapnr != X86_TRAP_UD)
        return NOTIFY_DONE;
    /* Only 64-bit user mode (CS RPL==3 and not 32-bit compat 0x23) */
    if ((regs->cs & 3ULL) != 3ULL || regs->cs == 0x23ULL)
        return NOTIFY_DONE;

    if (copy_from_user_nofault(insn, (const void *)regs->ip, 15UL) != 0) {
        avail = 0;
        for (int n = 14; n >= 5; n--) {
            if (copy_from_user_nofault(insn, (const void *)regs->ip, (unsigned long)n) == 0) {
                avail = n;
                break;
            }
        }
        if (avail < 5)
            return NOTIFY_DONE;
    }

    /* 3-byte VEX prefix 0xC4, map 0F38 (mmmmm == 2) */
    if (insn[0] != 0xC4 || (insn[1] & 0x1F) != 0x02)
        return NOTIFY_DONE;

    int R = ((insn[1] >> 7) & 1) ^ 1;
    int X = ((insn[1] >> 6) & 1) ^ 1;
    int B = ((insn[1] >> 5) & 1) ^ 1;

    int W = (insn[2] >> 7) & 1;
    int vvvv_reg = ((~insn[2]) >> 3) & 0x0F;
    int L = (insn[2] >> 2) & 1;
    int pp = insn[2] & 0x03;
    u8 op = insn[3];

    int kind = 0;
    /* 1..4: AVX-VNNI (W=0, pp=1, op 0x50..0x53) */
    if (W == 0 && pp == 1 && op >= 0x50 && op <= 0x53) {
        kind = 1 + (op - 0x50);
    } else if (W == 0 && (op == 0x50 || op == 0x51) && (pp == 0 || pp == 2 || pp == 3)) {
        /* 5..12: AVX-VNNI-INT8 */
        kind = 5 + pp * 2 + (op - 0x50);
    } else if (W == 1 && pp == 1 && (op == 0xB4 || op == 0xB5)) {
        /* 20..21: AVX-IFMA (vpmadd52luq / vpmadd52huq) */
        kind = 20 + (op - 0xB4);
    } else {
        return NOTIFY_DONE;
    }

    u8 modrm = insn[4];
    int mod = (modrm >> 6) & 3;
    int dst_reg = (R << 3) | ((modrm >> 3) & 7);
    int rm_low = modrm & 7;
    int pos = 5;

    union vec256 dst, src1, src2;
    if (mod != 3) {
        u64 ea = 0;
        if (rm_low == 4) {
            if (pos >= avail) return NOTIFY_DONE;
            u8 sib = insn[pos++];
            int scale = (sib >> 6) & 3;
            int idx_reg = (X << 3) | ((sib >> 3) & 7);
            int base_low = sib & 7;
            int base_reg = (B << 3) | base_low;
            u64 idx_val = (idx_reg == 4) ? 0ULL : (get_gpr(regs, idx_reg) << scale);
            u64 base_val = 0;
            s64 disp = 0;
            if (mod == 0 && base_low == 5) {
                if (pos + 4 > avail) return NOTIFY_DONE;
                s32 d32;
                __builtin_memcpy(&d32, &insn[pos], 4);
                pos += 4;
                disp = (s64)d32;
            } else {
                base_val = get_gpr(regs, base_reg);
                if (mod == 1) {
                    if (pos + 1 > avail) return NOTIFY_DONE;
                    disp = (s64)(s8)insn[pos++];
                } else if (mod == 2) {
                    if (pos + 4 > avail) return NOTIFY_DONE;
                    s32 d32;
                    __builtin_memcpy(&d32, &insn[pos], 4);
                    pos += 4;
                    disp = (s64)d32;
                }
            }
            ea = base_val + idx_val + (u64)disp;
        } else if (mod == 0 && rm_low == 5) {
            if (pos + 4 > avail) return NOTIFY_DONE;
            s32 d32;
            __builtin_memcpy(&d32, &insn[pos], 4);
            pos += 4;
            ea = regs->ip + (u64)pos + (u64)(s64)d32;
        } else {
            int base_reg = (B << 3) | rm_low;
            u64 base_val = get_gpr(regs, base_reg);
            s64 disp = 0;
            if (mod == 1) {
                if (pos + 1 > avail) return NOTIFY_DONE;
                disp = (s64)(s8)insn[pos++];
            } else if (mod == 2) {
                if (pos + 4 > avail) return NOTIFY_DONE;
                s32 d32;
                __builtin_memcpy(&d32, &insn[pos], 4);
                pos += 4;
                disp = (s64)d32;
            }
            ea = base_val + (u64)disp;
        }
        unsigned long vbytes = L ? 32UL : 16UL;
        if (copy_from_user_nofault(&src2, (const void *)ea, vbytes) != 0)
            return NOTIFY_DONE;
    }

    /* Disable local IRQs and ensure current thread's FPU/YMM state is loaded in hardware */
    u64 irq_flags;
    __asm__ volatile("pushfq; popq %0; cli" : "=r"(irq_flags) :: "memory");
    switch_fpu_return();

    if (!avx_state_usable()) {
        __asm__ volatile("pushq %0; popfq" :: "r"(irq_flags) : "memory", "cc");
        return NOTIFY_DONE;
    }

    if (mod == 3) {
        int src2_reg = (B << 3) | rm_low;
        get_ymm(src2_reg, &src2);
    }
    get_ymm(dst_reg, &dst);
    get_ymm(vvvv_reg, &src1);

    int lanes32 = L ? 8 : 4;
    if (kind == 1 || kind == 2) {
        /* VPDPBUSD / VPDPBUSDS: u8 * s8 -> s32 */
        for (int i = 0; i < lanes32; i++) {
            s64 p = (s64)(u32)src1.u8v[4*i + 0] * (s64)src2.s8v[4*i + 0]
                  + (s64)(u32)src1.u8v[4*i + 1] * (s64)src2.s8v[4*i + 1]
                  + (s64)(u32)src1.u8v[4*i + 2] * (s64)src2.s8v[4*i + 2]
                  + (s64)(u32)src1.u8v[4*i + 3] * (s64)src2.s8v[4*i + 3];
            if (kind == 1)
                dst.u32v[i] = dst.u32v[i] + (u32)p;
            else
                dst.s32v[i] = sat_s32((s64)dst.s32v[i] + p);
        }
    } else if (kind == 3 || kind == 4) {
        /* VPDPWSSD / VPDPWSSDS: s16 * s16 -> s32 */
        for (int i = 0; i < lanes32; i++) {
            s64 p = (s64)src1.s16v[2*i + 0] * (s64)src2.s16v[2*i + 0]
                  + (s64)src1.s16v[2*i + 1] * (s64)src2.s16v[2*i + 1];
            if (kind == 3)
                dst.u32v[i] = dst.u32v[i] + (u32)p;
            else
                dst.s32v[i] = sat_s32((s64)dst.s32v[i] + p);
        }
    } else if (kind >= 5 && kind <= 12) {
        /* AVX-VNNI-INT8: pp=0 (u8*u8), pp=2 (s8*u8), pp=3 (s8*s8) */
        int sat = (op == 0x51);
        for (int i = 0; i < lanes32; i++) {
            s32 p = 0;
            for (int j = 0; j < 4; j++) {
                s32 a = (pp == 0) ? (s32)(u32)src1.u8v[4*i + j] : (s32)src1.s8v[4*i + j];
                s32 b = (pp == 3) ? (s32)src2.s8v[4*i + j] : (s32)(u32)src2.u8v[4*i + j];
                p += a * b;
            }
            if (!sat)
                dst.u32v[i] = dst.u32v[i] + (u32)p;
            else
                dst.s32v[i] = sat_s32((s64)dst.s32v[i] + (s64)p);
        }
    } else if (kind == 20 || kind == 21) {
        /* AVX-IFMA: VPMADD52LUQ / VPMADD52HUQ */
        int lanes64 = L ? 4 : 2;
        u64 mask52 = (1ULL << 52) - 1ULL;
        for (int i = 0; i < lanes64; i++) {
            unsigned __int128 prod = (unsigned __int128)(src1.u64v[i] & mask52)
                                   * (unsigned __int128)(src2.u64v[i] & mask52);
            if (kind == 20)
                dst.u64v[i] += (u64)prod & mask52;
            else
                dst.u64v[i] += (u64)(prod >> 52);
        }
    }

    if (L)
        set_ymm(dst_reg, &dst);
    else
        set_xmm(dst_reg, &dst);

    __asm__ volatile("pushq %0; popfq" :: "r"(irq_flags) : "memory", "cc");

    regs->ip += (u64)pos;
    return NOTIFY_STOP;
}

static struct notifier_block vnni_nb = {
    .notifier_call = vnni_die_handler,
    .next = (struct notifier_block *)0,
    .priority = 0x7fffffff,
};

__attribute__((used, section(".init.text")))
int init_module_impl(void) {
    int rc = register_die_notifier(&vnni_nb);
    _printk("\x01" "6avx_vnni_emu: VEX AVX-VNNI/IFMA #UD trap emulator registered (rc=%d)\n", rc);
    return rc;
}

__attribute__((used, section(".exit.text")))
void cleanup_module_impl(void) {
    unregister_die_notifier(&vnni_nb);
}
