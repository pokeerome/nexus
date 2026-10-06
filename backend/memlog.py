def _read_mb(path):
    try:
        with open(path) as f:
            return round(int(f.read().strip()) / 1024 / 1024)
    except Exception:
        return None


def container_memory_mb():
    return _read_mb("/sys/fs/cgroup/memory.current") or _read_mb(
        "/sys/fs/cgroup/memory/memory.usage_in_bytes"
    )


def process_memory_mb():
    try:
        with open("/proc/self/status") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    return round(int(line.split()[1]) / 1024)
    except Exception:
        return None
    return None


def log_memory(label: str) -> None:
    print(
        f"[memory] {label}: container={container_memory_mb()} MB, "
        f"this process={process_memory_mb()} MB",
        flush=True,
    )