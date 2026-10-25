#!/usr/bin/env python3
"""Grant execmem permission to system_server only, to allow SwiftShader Vulkan JIT."""

RULES = """
allow system_server self:process execmem;
"""

def get_selinux_rules() -> str:
    return RULES.strip()

if __name__ == '__main__':
    print("SELinux policy extensions for Googlebook OS SwiftShader JIT:")
    print(RULES)
