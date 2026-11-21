import os
import re
import glob

def patch_source_files():
    print("🚀 开始修改 mdvdb 源码...")
    
    # 1. 注入安全软锁降级逻辑
    lock_patches = {
        "src/index/state.rs": [
            (r'fn acquire_write_lock\(index_path: &Path\) -> Result<std::fs::File> \{', r'#[allow(unreachable_code, unused_variables)]\nfn acquire_write_lock(index_path: &Path) -> Result<std::fs::File> {'),
            (r'(Err\(std::fs::TryLockError::Error\(e\)\) => return Err\(Error::Io\(e\)\),)',
             r'''#[cfg(target_os = "android")]
            Err(std::fs::TryLockError::Error(ref e)) if e.kind() == std::io::ErrorKind::Unsupported => {
                for _ in 0..ATTEMPTS {
                    match std::fs::OpenOptions::new().write(true).create_new(true).open(&lock_path) {
                        Ok(lock_file) => return Ok(lock_file),
                        Err(err) if err.kind() == std::io::ErrorKind::AlreadyExists => {
                            std::thread::sleep(std::time::Duration::from_millis(RETRY_DELAY_MS));
                        }
                        Err(err) => return Err(Error::Io(err)),
                    }
                }
                return Err(Error::IndexBusy { path: index_path.to_path_buf() });
            }
            \1''')
        ],
        "src/config.rs": [
            (r'pub\(crate\) fn acquire_config_lock', r'#[allow(unreachable_code, unused_variables)]\npub(crate) fn acquire_config_lock'),
            (r'(Err\(std::fs::TryLockError::Error\(e\)\) => return Err\(Error::Io\(e\)\),)',
             r'''#[cfg(target_os = "android")]
            Err(std::fs::TryLockError::Error(ref e)) if e.kind() == std::io::ErrorKind::Unsupported => {
                for _ in 0..ATTEMPTS {
                    match std::fs::OpenOptions::new().write(true).create_new(true).open(&lock_path) {
                        Ok(lock_file) => return Ok(ConfigLockGuard { _file: lock_file }),
                        Err(err) if err.kind() == std::io::ErrorKind::AlreadyExists => {
                            std::thread::sleep(RETRY_DELAY);
                        }
                        Err(err) => return Err(Error::Config(format!("lock error: {err}"))),
                    }
                }
                return Err(Error::Config("Config lock timeout".into()));
            }
            \1''')
        ],
        "src/modules.rs": [
            (r'pub fn acquire_module_run_lock\(project_root: &Path\)', r'#[allow(unreachable_code, unused_variables)]\npub fn acquire_module_run_lock(project_root: &Path)'),
            (r'(Err\(std::fs::TryLockError::Error\(e\)\) => return Err\(crate::Error::Io\(e\)\),)',
             r'''#[cfg(target_os = "android")]
            Err(std::fs::TryLockError::Error(ref e)) if e.kind() == std::io::ErrorKind::Unsupported => {
                for _ in 0..ATTEMPTS {
                    match std::fs::OpenOptions::new().write(true).create_new(true).open(&lock_path) {
                        Ok(lock_file) => return Ok(ModuleRunLock { _file: lock_file, root_guard }),
                        Err(err) if err.kind() == std::io::ErrorKind::AlreadyExists => {
                            std::thread::sleep(RETRY_DELAY);
                        }
                        Err(err) => return Err(crate::Error::Config(format!("Module lock error: {err}"))),
                    }
                }
                return Err(crate::Error::Config("Module lock timeout".into()));
            }
            \1''')
        ]
    }
    
    for file, rules in lock_patches.items():
        if not os.path.exists(file): continue
        with open(file, "r", encoding="utf-8") as f: content = f.read()
        for pattern, replacement in rules:
            if "Unsupported =>" not in content:
                content = re.sub(pattern, replacement, content)
        with open(file, "w", encoding="utf-8") as f: f.write(content)
    print("✅ 已注入 Android 安全软锁降级逻辑")

    # 2. 修复 HOME 兜底
    with open("src/config.rs", "r", encoding="utf-8") as f: content = f.read()
    old_code = 'dirs::home_dir().map(|h| h.join(".mdvdb"))'
    new_code = '''if let Ok(home) = std::env::var("HOME") {
            if !home.is_empty() { return Some(PathBuf::from(home).join(".mdvdb")); }
        }
        dirs::home_dir().map(|h| h.join(".mdvdb"))'''
    if new_code not in content:
        content = content.replace(old_code, new_code)
        with open("src/config.rs", "w", encoding="utf-8") as f: f.write(content)
        print("✅ 已注入 HOME 环境变量兜底")

    # 3. 支持 .py 后缀
    py_rules = {
        "src/discovery.rs": [
            (r'if path\.extension\(\)\.and_then\(\|e\| e\.to_str\(\)\) != Some\("md"\)', r'if !matches!(path.extension().and_then(|e| e.to_str()), Some("md" | "py"))'),
            (r'if relative_path\.extension\(\)\.and_then\(\|e\| e\.to_str\(\)\) != Some\("md"\)', r'if !matches!(relative_path.extension().and_then(|e| e.to_str()), Some("md" | "py"))')
        ],
        "src/watcher.rs": [
            (r'if from\.extension\(\)\.and_then\(\|e\| e\.to_str\(\)\) == Some\("md"\)', r'if matches!(from.extension().and_then(|e| e.to_str()), Some("md" | "py"))'),
            (r'if rel\.extension\(\)\.and_then\(\|e\| e\.to_str\(\)\) == Some\("md"\)', r'if matches!(rel.extension().and_then(|e| e.to_str()), Some("md" | "py"))')
        ],
        "src/main.rs": [
            (r'e\.path\(\)\.extension\(\)\.is_some_and\(\|ext\| ext == "md"\)', r'e.path().extension().is_some_and(|ext| ext == "md" || ext == "py")')
        ]
    }
    
    for file, rules in py_rules.items():
        if not os.path.exists(file): continue
        with open(file, "r", encoding="utf-8") as f: content = f.read()
        for pattern, replacement in rules:
            content = re.sub(pattern, replacement, content)
        with open(file, "w", encoding="utf-8") as f: f.write(content)
    print("✅ 已注入 .py 后缀支持")

def patch_usearch_cargo():
    print("\n🚀 开始修补 usearch 缓存以兼容 Android...")
    search_paths = glob.glob(os.path.expanduser("~/.cargo/registry/src/*/usearch-2.24.0"))
    if not search_paths: return
        
    usearch_dir = search_paths[0]
    build_rs = os.path.join(usearch_dir, "build.rs")
    lib_c = os.path.join(usearch_dir, "simsimd/c/lib.c")
    lib_cpp = os.path.join(usearch_dir, "simsimd/c/lib.cpp")
    
    if os.path.exists(lib_c):
        os.rename(lib_c, lib_cpp)
    if os.path.exists(build_rs):
        with open(build_rs, "r", encoding="utf-8") as f: content = f.read()
        content = content.replace("simsimd/c/lib.c", "simsimd/c/lib.cpp")
        content = content.replace('.flag("-std=c++17")', '')
        content = content.replace('.flag_if_supported("-std=c++17")', '')
        content = content.replace('.flag_if_supported()', '')
        with open(build_rs, "w", encoding="utf-8") as f: f.write(content)
        
    h_file = os.path.join(usearch_dir, "simsimd/include/simsimd/simsimd.h")
    if os.path.exists(h_file):
        with open(h_file, "r", encoding="utf-8") as f: content = f.read()
        if "#include <cstdint>" not in content:
            with open(h_file, "w", encoding="utf-8") as f: f.write("#include <cstdint>\n" + content)
    print("✅ usearch 缓存修补完成")

if __name__ == "__main__":
    patch_source_files()
    patch_usearch_cargo()
    print("\n🎉 所有 Android 兼容补丁已应用完毕！")
