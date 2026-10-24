#!/usr/bin/env python3
"""Grant execmem permission to system_server and appdomain to allow SwiftShader Vulkan JIT."""

RULES = """
allow system_server self:process execmem;
allow appdomain self:process execmem;
allow untrusted_app_all self:process execmem;
allow shell self:process execmem;
allow surfaceflinger self:process execmem;
"""

def get_selinux_rules() -> str:
    return RULES.strip()

if __name__ == '__main__':
    print("SELinux policy extensions for Googlebook OS SwiftShader JIT:")
    print(RULES)
