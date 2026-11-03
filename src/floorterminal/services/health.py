"""Best-effort, read-only platform health observations; no shell or network."""

from pathlib import Path


def system_observations():
    report = {"warnings": []}
    try:
        fields = {}
        for line in Path("/proc/meminfo").read_text(encoding="ascii").splitlines():
            key, value = line.split(":", 1)
            fields[key] = int(value.strip().split()[0])
        available, total = fields["MemAvailable"], fields["MemTotal"]
        report["memory_available_mb"] = round(available / 1024)
        if available < max(64 * 1024, total // 20):
            report["warnings"].append("Low available system memory")
    except (OSError, ValueError, KeyError, IndexError):
        pass
    try:
        temperature = (
            int(Path("/sys/class/thermal/thermal_zone0/temp").read_text().strip())
            / 1000
        )
        if -20 <= temperature <= 150:
            report["temperature_c"] = round(temperature, 1)
            if temperature >= 80:
                report["warnings"].append("High device temperature; check cooling")
    except (OSError, ValueError):
        pass
    return report
