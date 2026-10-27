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

static inline s32 read_s32(const u8 *p) {
    u32 v = (u32)p[0] | ((u32)p[1] << 8) | ((u32)p[2] << 16) | ((u32)p[3] << 24);
    return (s32)v;
}

static inline s32 sat_s32(s64 v) {
    if (v > 2147483647LL) return 2147483647;
    if (v < -2147483648LL) return (s32)(-2147483647 - 1);
    return (s32)v;
}

/* GF(2^8) mod x^8 + x^4 + x^3 + x + 1 (0x11B) helpers for GFNI and VAES */
static inline u8 gf2p8_mul(u8 a, u8 b) {
    u8 p = 0;
    for (int i = 0; i < 8; i++) {
        if (b & 1) p ^= a;
        u8 hi = a & 0x80;
        a <<= 1;
        if (hi) a ^= 0x1b;
        b >>= 1;
    }
    return p;
}

static inline u8 gf2p8_inv(u8 a) {
    u8 a2 = gf2p8_mul(a, a);
    u8 a4 = gf2p8_mul(a2, a2);
    u8 a8 = gf2p8_mul(a4, a4);
    u8 a16 = gf2p8_mul(a8, a8);
    u8 a32 = gf2p8_mul(a16, a16);
    u8 a64 = gf2p8_mul(a32, a32);
    u8 a128 = gf2p8_mul(a64, a64);
    return gf2p8_mul(gf2p8_mul(gf2p8_mul(a128, a64), gf2p8_mul(a32, a16)),
                     gf2p8_mul(gf2p8_mul(a8, a4), a2));
}

static inline u8 parity8(u8 x) {
    x ^= x >> 4;
    x ^= x >> 2;
    x ^= x >> 1;
    return x & 1;
}

static inline u8 gf2p8_affine_byte(u64 mat, u8 x, u8 imm) {
    u8 res = 0;
    for (int bit = 0; bit < 8; bit++) {
        u8 row = (u8)(mat >> ((7 - bit) * 8));
        res |= (u8)(parity8(row & x) << bit);
    }
    return res ^ imm;
}

static inline u8 aes_sbox(u8 x) {
    u8 s = gf2p8_inv(x);
    u8 r = s;
    r ^= (u8)((s << 1) | (s >> 7));
    r ^= (u8)((s << 2) | (s >> 6));
    r ^= (u8)((s << 3) | (s >> 5));
    r ^= (u8)((s << 4) | (s >> 4));
    return r ^ 0x63;
}

static inline u8 aes_isbox(u8 y) {
    u8 s = (u8)((y << 1) | (y >> 7))
         ^ (u8)((y << 3) | (y >> 5))
         ^ (u8)((y << 6) | (y >> 2))
         ^ 0x05;
    return gf2p8_inv(s);
}

static void emu_aes_lane(u8 *out, const u8 *st, const u8 *rk, int dec, int last) {
    u8 t[16];
    if (!dec) {
        u64 sr_perm = 0xB61C72D83E94FA50ULL;
        for (int i = 0; i < 16; i++)
            t[i] = aes_sbox(st[(sr_perm >> (4 * i)) & 0xF]);
        if (!last) {
            for (int c = 0; c < 4; c++) {
                u8 s0 = t[4*c+0], s1 = t[4*c+1], s2 = t[4*c+2], s3 = t[4*c+3];
                out[4*c+0] = gf2p8_mul(s0, 2) ^ gf2p8_mul(s1, 3) ^ s2 ^ s3 ^ rk[4*c+0];
                out[4*c+1] = s0 ^ gf2p8_mul(s1, 2) ^ gf2p8_mul(s2, 3) ^ s3 ^ rk[4*c+1];
                out[4*c+2] = s0 ^ s1 ^ gf2p8_mul(s2, 2) ^ gf2p8_mul(s3, 3) ^ rk[4*c+2];
                out[4*c+3] = gf2p8_mul(s0, 3) ^ s1 ^ s2 ^ gf2p8_mul(s3, 2) ^ rk[4*c+3];
            }
        } else {
            for (int i = 0; i < 16; i++) out[i] = t[i] ^ rk[i];
        }
    } else {
        u64 isr_perm = 0x369CF258BE147AD0ULL;
        for (int i = 0; i < 16; i++)
            t[i] = aes_isbox(st[(isr_perm >> (4 * i)) & 0xF]);
        if (!last) {
            for (int c = 0; c < 4; c++) {
                u8 s0 = t[4*c+0], s1 = t[4*c+1], s2 = t[4*c+2], s3 = t[4*c+3];
                out[4*c+0] = gf2p8_mul(s0, 14) ^ gf2p8_mul(s1, 11) ^ gf2p8_mul(s2, 13) ^ gf2p8_mul(s3, 9)  ^ rk[4*c+0];
                out[4*c+1] = gf2p8_mul(s0, 9)  ^ gf2p8_mul(s1, 14) ^ gf2p8_mul(s2, 11) ^ gf2p8_mul(s3, 13) ^ rk[4*c+1];
                out[4*c+2] = gf2p8_mul(s0, 13) ^ gf2p8_mul(s1, 9)  ^ gf2p8_mul(s2, 14) ^ gf2p8_mul(s3, 11) ^ rk[4*c+2];
                out[4*c+3] = gf2p8_mul(s0, 11) ^ gf2p8_mul(s1, 13) ^ gf2p8_mul(s2, 9)  ^ gf2p8_mul(s3, 14) ^ rk[4*c+3];
            }
        } else {
            for (int i = 0; i < 16; i++) out[i] = t[i] ^ rk[i];
        }
    }
}

static inline u32 rotr32(u32 x, int n) { return (x >> n) | (x << (32 - n)); }
static inline u32 rotl32(u32 x, int n) { return (x << n) | (x >> (32 - n)); }

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
        for (int n = 14; n >= 4; n--) {
            if (copy_from_user_nofault(insn, (const void *)regs->ip, (unsigned long)n) == 0) {
                avail = n;
                break;
            }
        }
        if (avail < 4)
            return NOTIFY_DONE;
    }

    int is_vex = 0;
    int R = 0, X = 0, B = 0, W = 0, vvvv_reg = 0, L = 0, pp = 0;
    int mmmmm = 0;
    u8 op = 0;
    int pos = 0;

    if (insn[0] == 0xC4) {
        if (avail < 5)
            return NOTIFY_DONE;
        is_vex = 1;
        mmmmm = insn[1] & 0x1F;
        if (mmmmm != 2 && mmmmm != 3)
            return NOTIFY_DONE;
        R = ((insn[1] >> 7) & 1) ^ 1;
        X = ((insn[1] >> 6) & 1) ^ 1;
        B = ((insn[1] >> 5) & 1) ^ 1;
        W = (insn[2] >> 7) & 1;
        vvvv_reg = ((~insn[2]) >> 3) & 0x0F;
        L = (insn[2] >> 2) & 1;
        pp = insn[2] & 0x03;
        op = insn[3];
        pos = 4;
    } else {
        int has_66 = 0, has_f2 = 0, has_f3 = 0, bad_pfx = 0;
        while (pos < 4 && pos < avail) {
            u8 b = insn[pos];
            if (b == 0x66) { has_66 = 1; pos++; }
            else if (b == 0xF2) { has_f2 = 1; pos++; }
            else if (b == 0xF3) { has_f3 = 1; pos++; }
            else if (b == 0x26 || b == 0x2E || b == 0x36 || b == 0x3E) { pos++; }
            else if (b == 0x64 || b == 0x65 || b == 0x67) { bad_pfx = 1; pos++; }
            else break;
        }
        if (bad_pfx || has_f2 || has_f3)
            return NOTIFY_DONE;
        if (pos < avail && (insn[pos] & 0xF0) == 0x40) {
            u8 rex = insn[pos++];
            W = (rex >> 3) & 1;
            R = (rex >> 2) & 1;
            X = (rex >> 1) & 1;
            B = rex & 1;
        }
        if (pos + 4 > avail || insn[pos] != 0x0F)
            return NOTIFY_DONE;
        u8 esc = insn[pos + 1];
        if (esc == 0x38) mmmmm = 2;
        else if (esc == 0x3A) mmmmm = 3;
        else return NOTIFY_DONE;
        op = insn[pos + 2];
        pp = has_66 ? 1 : 0;
        pos += 3;
    }

    int kind = 0;
    int has_imm = 0;

    if (is_vex && mmmmm == 2) {
        if (W == 0 && pp == 1 && op >= 0x50 && op <= 0x53) {
            kind = 1 + (op - 0x50); /* AVX-VNNI */
        } else if (W == 0 && (op == 0x50 || op == 0x51) && (pp == 0 || pp == 2 || pp == 3)) {
            kind = 5 + pp * 2 + (op - 0x50); /* AVX-VNNI-INT8 */
        } else if (W == 1 && pp == 1 && (op == 0xB4 || op == 0xB5)) {
            kind = 20 + (op - 0xB4); /* AVX-IFMA */
        } else if (W == 0 && pp == 1 && op == 0xCF) {
            kind = 30; /* VGF2P8MULB */
        } else if (pp == 1 && op >= 0xDC && op <= 0xDF) {
            kind = 40 + (op - 0xDC); /* VAESENC / VAESENCLAST / VAESDEC / VAESDECLAST */
        }
    } else if (is_vex && mmmmm == 3) {
        if (W == 1 && pp == 1 && (op == 0xCE || op == 0xCF)) {
            kind = 31 + (op - 0xCE); /* VGF2P8AFFINEQB / VGF2P8AFFINEINVQB */
            has_imm = 1;
        } else if (pp == 1 && op == 0x44) {
            kind = 44; /* VPCLMULQDQ */
            has_imm = 1;
        }
    } else if (!is_vex && mmmmm == 2) {
        if (pp == 1 && op == 0xCF) {
            kind = 30; /* GF2P8MULB */
        } else if (pp == 1 && op >= 0xDC && op <= 0xDF) {
            kind = 40 + (op - 0xDC); /* AESENC / AESENCLAST / AESDEC / AESDECLAST */
        } else if (pp == 0 && op >= 0xC8 && op <= 0xCD) {
            kind = 50 + (op - 0xC8); /* SHA1NEXTE..SHA256MSG2 */
        }
    } else if (!is_vex && mmmmm == 3) {
        if (pp == 1 && (op == 0xCE || op == 0xCF)) {
            kind = 31 + (op - 0xCE); /* GF2P8AFFINEQB / GF2P8AFFINEINVQB */
            has_imm = 1;
        } else if (pp == 1 && op == 0x44) {
            kind = 44; /* PCLMULQDQ */
            has_imm = 1;
        } else if (pp == 0 && op == 0xCC) {
            kind = 56; /* SHA1RNDS4 */
            has_imm = 1;
        }
    }

    if (kind == 0 || pos >= avail)
        return NOTIFY_DONE;

    u8 modrm = insn[pos++];
    int mod = (modrm >> 6) & 3;
    int dst_reg = (R << 3) | ((modrm >> 3) & 7);
    int rm_low = modrm & 7;

    u64 ea = 0;
    int rip_rel = 0;
    s64 rip_disp = 0;

    if (mod != 3) {
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
                disp = (s64)read_s32(&insn[pos]);
                pos += 4;
            } else {
                base_val = get_gpr(regs, base_reg);
                if (mod == 1) {
                    if (pos + 1 > avail) return NOTIFY_DONE;
                    disp = (s64)(s8)insn[pos++];
                } else if (mod == 2) {
                    if (pos + 4 > avail) return NOTIFY_DONE;
                    disp = (s64)read_s32(&insn[pos]);
                    pos += 4;
                }
            }
            ea = base_val + idx_val + (u64)disp;
        } else if (mod == 0 && rm_low == 5) {
            if (pos + 4 > avail) return NOTIFY_DONE;
            rip_disp = (s64)read_s32(&insn[pos]);
            pos += 4;
            rip_rel = 1;
        } else {
            int base_reg = (B << 3) | rm_low;
            u64 base_val = get_gpr(regs, base_reg);
            s64 disp = 0;
            if (mod == 1) {
                if (pos + 1 > avail) return NOTIFY_DONE;
                disp = (s64)(s8)insn[pos++];
            } else if (mod == 2) {
                if (pos + 4 > avail) return NOTIFY_DONE;
                disp = (s64)read_s32(&insn[pos]);
                pos += 4;
            }
            ea = base_val + (u64)disp;
        }
    }

    u8 imm = 0;
    if (has_imm) {
        if (pos >= avail) return NOTIFY_DONE;
        imm = insn[pos++];
    }

    union vec256 dst, src1, src2, xmm0_v;
    if (mod != 3) {
        if (rip_rel)
            ea = regs->ip + (u64)pos + (u64)rip_disp;
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
    if (is_vex) {
        get_ymm(vvvv_reg, &src1);
    } else {
        for (int k = 0; k < 4; k++)
            src1.u64v[k] = dst.u64v[k];
    }
    if (kind == 53)
        get_ymm(0, &xmm0_v);

    int lanes32 = L ? 8 : 4;
    if (kind == 1 || kind == 2) {
        /* VPDPBUSD / VPDPBUSDS */
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
        /* VPDPWSSD / VPDPWSSDS */
        for (int i = 0; i < lanes32; i++) {
            s64 p = (s64)src1.s16v[2*i + 0] * (s64)src2.s16v[2*i + 0]
                  + (s64)src1.s16v[2*i + 1] * (s64)src2.s16v[2*i + 1];
            if (kind == 3)
                dst.u32v[i] = dst.u32v[i] + (u32)p;
            else
                dst.s32v[i] = sat_s32((s64)dst.s32v[i] + p);
        }
    } else if (kind >= 5 && kind <= 12) {
        /* AVX-VNNI-INT8 */
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
    } else if (kind == 30) {
        /* GF2P8MULB / VGF2P8MULB */
        int nbytes = L ? 32 : 16;
        for (int i = 0; i < nbytes; i++)
            dst.u8v[i] = gf2p8_mul(src1.u8v[i], src2.u8v[i]);
    } else if (kind == 31 || kind == 32) {
        /* GF2P8AFFINEQB / GF2P8AFFINEINVQB */
        int qwords = L ? 4 : 2;
        for (int q = 0; q < qwords; q++) {
            u64 mat = src2.u64v[q];
            for (int j = 0; j < 8; j++) {
                u8 x = src1.u8v[8*q + j];
                if (kind == 32)
                    x = gf2p8_inv(x);
                dst.u8v[8*q + j] = gf2p8_affine_byte(mat, x, imm);
            }
        }
    } else if (kind >= 40 && kind <= 43) {
        /* VAESENC / VAESENCLAST / VAESDEC / VAESDECLAST */
        int dec = (kind >= 42);
        int last = ((kind - 40) & 1);
        int lanes128 = L ? 2 : 1;
        for (int lane = 0; lane < lanes128; lane++)
            emu_aes_lane(&dst.u8v[16 * lane], &src1.u8v[16 * lane], &src2.u8v[16 * lane], dec, last);
    } else if (kind == 44) {
        /* VPCLMULQDQ / PCLMULQDQ */
        int lanes128 = L ? 2 : 1;
        for (int lane = 0; lane < lanes128; lane++) {
            u64 x = src1.u64v[2*lane + (imm & 1)];
            u64 y = src2.u64v[2*lane + ((imm >> 4) & 1)];
            u64 lo = 0, hi = 0;
            for (int k = 0; k < 64; k++) {
                if ((y >> k) & 1ULL) {
                    if (k == 0) {
                        lo ^= x;
                    } else {
                        lo ^= (x << k);
                        hi ^= (x >> (64 - k));
                    }
                }
            }
            dst.u64v[2*lane + 0] = lo;
            dst.u64v[2*lane + 1] = hi;
        }
    } else if (kind == 50) {
        /* SHA1NEXTE */
        u32 out3 = src2.u32v[3] + rotl32(src1.u32v[3], 30);
        dst.u32v[0] = src2.u32v[0];
        dst.u32v[1] = src2.u32v[1];
        dst.u32v[2] = src2.u32v[2];
        dst.u32v[3] = out3;
    } else if (kind == 51) {
        /* SHA1MSG1 */
        u32 w0 = src1.u32v[3], w1 = src1.u32v[2], w2 = src1.u32v[1], w3 = src1.u32v[0];
        u32 w4 = src2.u32v[3], w5 = src2.u32v[2];
        dst.u32v[3] = w2 ^ w0;
        dst.u32v[2] = w3 ^ w1;
        dst.u32v[1] = w4 ^ w2;
        dst.u32v[0] = w5 ^ w3;
    } else if (kind == 52) {
        /* SHA1MSG2 */
        u32 t3 = rotl32(src1.u32v[3] ^ src2.u32v[2], 1);
        u32 t2 = rotl32(src1.u32v[2] ^ src2.u32v[1], 1);
        u32 t1 = rotl32(src1.u32v[1] ^ src2.u32v[0], 1);
        u32 t0 = rotl32(src1.u32v[0] ^ t3, 1);
        dst.u32v[3] = t3;
        dst.u32v[2] = t2;
        dst.u32v[1] = t1;
        dst.u32v[0] = t0;
    } else if (kind == 53) {
        /* SHA256RNDS2 (dst=CDGH, src2=ABEF, xmm0=WK) */
        u32 A = src2.u32v[3], B = src2.u32v[2], E = src2.u32v[1], F = src2.u32v[0];
        u32 C = src1.u32v[3], D = src1.u32v[2], G = src1.u32v[1], H = src1.u32v[0];
        for (int i = 0; i < 2; i++) {
            u32 s1 = rotr32(E, 6) ^ rotr32(E, 11) ^ rotr32(E, 25);
            u32 ch = (E & F) ^ (~E & G);
            u32 t1 = H + s1 + ch + xmm0_v.u32v[i];
            u32 s0 = rotr32(A, 2) ^ rotr32(A, 13) ^ rotr32(A, 22);
            u32 maj = (A & B) ^ (A & C) ^ (B & C);
            u32 t2 = s0 + maj;
            H = G; G = F; F = E; E = D + t1;
            D = C; C = B; B = A; A = t1 + t2;
        }
        dst.u32v[3] = A;
        dst.u32v[2] = B;
        dst.u32v[1] = E;
        dst.u32v[0] = F;
    } else if (kind == 54) {
        /* SHA256MSG1 */
        u32 w0 = src1.u32v[0], w1 = src1.u32v[1], w2 = src1.u32v[2], w3 = src1.u32v[3], w4 = src2.u32v[0];
        dst.u32v[0] = w0 + (rotr32(w1, 7) ^ rotr32(w1, 18) ^ (w1 >> 3));
        dst.u32v[1] = w1 + (rotr32(w2, 7) ^ rotr32(w2, 18) ^ (w2 >> 3));
        dst.u32v[2] = w2 + (rotr32(w3, 7) ^ rotr32(w3, 18) ^ (w3 >> 3));
        dst.u32v[3] = w3 + (rotr32(w4, 7) ^ rotr32(w4, 18) ^ (w4 >> 3));
    } else if (kind == 55) {
        /* SHA256MSG2 */
        u32 w14 = src2.u32v[2], w15 = src2.u32v[3];
        u32 w16 = src1.u32v[0] + (rotr32(w14, 17) ^ rotr32(w14, 19) ^ (w14 >> 10));
        u32 w17 = src1.u32v[1] + (rotr32(w15, 17) ^ rotr32(w15, 19) ^ (w15 >> 10));
        dst.u32v[0] = w16;
        dst.u32v[1] = w17;
        dst.u32v[2] = src1.u32v[2] + (rotr32(w16, 17) ^ rotr32(w16, 19) ^ (w16 >> 10));
        dst.u32v[3] = src1.u32v[3] + (rotr32(w17, 17) ^ rotr32(w17, 19) ^ (w17 >> 10));
    } else if (kind == 56) {
        /* SHA1RNDS4 */
        u32 A = src1.u32v[3], B = src1.u32v[2], C = src1.u32v[1], D = src1.u32v[0];
        int func = imm & 3;
        u32 K = (func == 0) ? 0x5A827999U : (func == 1) ? 0x6ED9EBA1U : (func == 2) ? 0x8F1BBCDCU : 0xCA62C1D6U;
        u32 E = 0;
        for (int i = 0; i < 4; i++) {
            u32 wi = src2.u32v[3 - i];
            u32 f = (func == 0) ? ((B & C) ^ (~B & D))
                  : (func == 2) ? ((B & C) ^ (B & D) ^ (C & D))
                  : (B ^ C ^ D);
            u32 nextA = rotl32(A, 5) + f + E + wi + K;
            E = D; D = C; C = rotl32(B, 30); B = A; A = nextA;
        }
        dst.u32v[3] = A;
        dst.u32v[2] = B;
        dst.u32v[1] = C;
        dst.u32v[0] = D;
    }

    if (!is_vex || L)
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
    _printk("\x01" "6avx_vnni_emu: Alder Lake ISA #UD emulator (VNNI/GFNI/VAES/VPCLMUL/SHA) registered (rc=%d)\n", rc);
    return rc;
}

__attribute__((used, section(".exit.text")))
void cleanup_module_impl(void) {
    unregister_die_notifier(&vnni_nb);
}
